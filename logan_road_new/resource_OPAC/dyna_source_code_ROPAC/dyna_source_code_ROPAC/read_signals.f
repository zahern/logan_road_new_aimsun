     	subroutine read_signals()  
! --
! -- This subroutine reads the signal control data.
! -- 
! -- This subroutine is called from the input (to read the first signal
! -- setting plans) and from loop (to read subsequent signal setting plans).
! -- This subroutine does not call any other subroutines.
! --
! -- INPUT :
! -- fort.44 : the signal control input data file.
! -- OUTPUT :
! -- The adjusted arrays for signal timing
! --
     	use muc_mod

     	integer error,j,ntmp
        integer,allocatable::kgpointmp(:,:)
     	integer,allocatable:: CheckSignal(:,:)
     	integer TmpMnAph(100), TmpMJAph(100)

	allocate(CheckSignal(noofnodes,2))
	allocate(kgpointmp(noofarcs+1,2),stat=error)

! --
! -- Initialization of relevent arrays.
! --
     	CheckSignal(:,:) = 0
     	kgpoint(:)=0
	kgpointmp(:,:)=0
     	gcratio(:)=0
     	movement(:,:,:)=0
     	SignalPreventFor(:,:)=1 ! default all prevented
     	SignalPreventBack(:,:)=1 ! default all prevented
! --
! -- kg is a counter for the number of phases in the whole network.
! --
     	kg=1
! --
! -- read the control type data from the input file.
! --
! -- Then, sort all phases in the network into one list (the counter kg).
! -- kgpoint is the pointer for the staring phase for each node (out of
! -- the kg phases).
! --
	 icount = 0

C        print *, 100
!     do 10 i=1,noofnodes-noof_master_destinations
     	do 10 i=1,noofnodes_org

         kgpoint(i)=kg
    
	     read(44,*,iostat=error) (node(i,j),j=1,4)
	     
! check input errors	
	     if(error.ne.0) then
           write(911,*) 'Error when reading control.dat'
	       stop
	     endif
!         if(node(i,2).lt.1) then ! check signal type input error

C        print *, 1001,i
! inputs out-of-range control type
c- change required to enable adaptive control
         if(node(i,2).ne.9) then ! check signal type input error
         if(node(i,2).lt.1.or.node(i,2).gt.6) then ! check signal type input error
           write(911,*) "Error in control.dat"
        write(911,*) "node", node(i,1),"has an invalid control type"
	write(911,*) "the control type should be between 1 and 6, or 9"
		   Stop
        endif
        endif 
 
C        print *, 1002		 

	     node(i,1) = idnum(node(i,1)) !G
c- change required to enable adaptive control		 
         if(node(i,2).eq.4.or.node(i,2).eq.5.or.node(i,2).eq.9) then !SIGNAL IS PRESENT
	       icount=icount+1
	       CheckSignal(icount,1) = node(i,1)
	       CheckSignal(icount,2) = node(i,3)
	       kgpointmp(icount,1)= i
	       kgpointmp(icount,2)= kg
           kg=kg+node(i,3)
	     else !stop, no control, yield, relax the SignalPreventFor to be 0
           do KM = backpointr(node(i,1)),backpointr(node(i,1)+1)-1 ! for all inbound links (back)
             do JM = 1, llink(BackToForLink(KM),nu_mv+1) ! for all outbound links of the inbound link
                SignalPreventFor(BackToForLink(KM),:) = 0
      SignalPreventBack(ForToBackLink(llink(BackToForLink(KM),JM)),:)=0
	         enddo
	       enddo
           if(node(i,2).eq.2.or.node(i,2).eq.6) then 
		        SignCount=SignCount+1 !yield or two-way stop
           endif
         endif
10 	continue
     	kgpoint(noofnodes+1)=kg
     	icountfinal=icount
     	kg=kg-1

C        print *, 1003
! --
! -- Read the signal phasing information for each phase.
! -- 
     	if(kg.gt.0) then  !FBA Block
	 icount = 1
	 icount2 = 1
	 icount3 = 0
	  
	  do 192 i=1,kg
        read(44,*,iostat=error) itmp,(nsign(i,j),j=1,9)
	    if(error.ne.0) then
          write(911,*) 'Error when reading control.dat'
	      stop
	    endif

	    if(idnum(itmp).eq.CheckSignal(icount2,1)) then
	      icount3 = icount3 + 1
	    else
	      if(icount3.ne.CheckSignal(icount2,2)) then
			write(911,*) 'error in matching signals'
            write(911,*) 'node', itmp, 'phase',nsign(i,1)
       write(911,*) "icount3, CheckSignal(icount2,2)",icount3,
     + CheckSignal(icount2,2)
			stop
	      endif
	      icount3 = 1
	      icount2 = icount2 + 1
	    endif

	    icount=0
		do ii = 6, 9						!
	      if (nsign(i,ii).ne.0) then		!
	        icount=icount+1					!
	      endif								!
	    enddo								!
	    if(icount.ne.nsign(i,5)) then		!
		 write(911,*) "Number of inbound links for node", itmp
          write(911,*) "is not specified correctly"
	      write(911,*) "Phase", nsign(i,1)
		  write(911,*) "Read as ", nsign(i,5), "counted as", icount
	     stop
	    endif
! --  convert to internal numbering system	    
	    if(nsign(i,6).gt.0) nsign(i,6) = idnum(nsign(i,6)) !G
	    if(nsign(i,7).gt.0) nsign(i,7) = idnum(nsign(i,7)) !G
 	    if(nsign(i,8).gt.0) nsign(i,8) = idnum(nsign(i,8)) !G
	    if(nsign(i,9).gt.0) nsign(i,9) = idnum(nsign(i,9)) !G


! --
! -- for the first signal timing plan, set the starting and ending times for
! -- the green and yellow times for each phase.
! -- Note : for the subsequent signal timing plans, the starting and ending
! -- times are alreay set based on the preceeding signal setting plan.
! -- Therefore, there is no need to set them again.
! -- 
          if(isigcount.eq.1) then
            do j=12,14
              nsign(i,j)=strtsig(isigcount)*60
            end do
          endif

! -- convert the node (in the nsign array) to link by recognizing
! -- the upstream node and the downstream nodes.
       do ii=6,nsign(i,5)+5
	     ntmp = nsign(i,ii)
	     if(GetFLinkFromNode(ntmp,idnum(itmp)).eq.0) then
	write(911,*) 'error in signal file, link doesnt exist'
	write(911,*) 'inbound',nodenum(ntmp),'signal node',itmp
	write(911,'("signal node",i7," Phase",i3," inbound nodes",
     +  3i10)') itmp,nsign(i,1),nodenum(nsign(i,6)),
     +  nodenum(nsign(i,7)),nodenum(nsign(i,8))
	       stop
           else
        nsign(i,ii) = GetFLinkFromNode(ntmp,idnum(itmp))
	  endif 
       end do

! --
! -- Read the movement data for each phase and each link which is allowed
! -- to utilize the intersection during each phase.
! -- nsign(i,5) : number of approaches which are allowed to move during phase i
! --
! -- 
! -- ifrom : the upstream node of the current approach
! -- ito : the downstream node of the current approach
! -- iphase : the current phase number
! -- nmvm : number of movements allowed from the current approach
! -- almov : a list of nodes to which the movements from the current
! --         approach are allowed.
! --
C        print *, 1004
		
      	do i1=1,nsign(i,5) !# of inbound links
!       read(44,66) ifrom,ito,iphasek,nmvm,(almov(i1,iin),iin=1,nmvm)
        read(44,*,iostat=error)ifrom,ito,iphasek,nmvm,
     +  (almov(i1,iin),iin=1,nmvm)
	  if(error.ne.0) then
         write(911,*) 'Error when reading phasing in control.dat'
	   stop
	  endif

	  if(idnum(ifrom).ne.iunod(nsign(i,5+i1))) then
		 write(911,'("inbound node",i5," for node",i5," at 
     + phase",i5," is not correct")')ifrom,ito,iphasek
	     stop
	  endif
	  do mm = 1, nmvm						                   !G
	    if(almov(i1,mm).gt.0) almov(i1,mm)=idnum(almov(i1,mm)) !G
	  enddo								                       !G
! -- make movement to the centroid allowed for all phases
        if(iConZone(idnum(ito),1).gt.0) then
	    do mpp= 1, iConZone(idnum(ito),1)
           nmvm = nmvm + 1
       almov(i1,nmvm)=
     + destination(MasterDest(iConZone(idnum(ito),mpp+1)))
	    enddo
        endif

66      format(15i7)
         j=nsign(i,i1+5)
           do ka=1,llink(j,nu_mv+1)
            do ia=1,nmvm
              if(idnod(llink(j,ka)).eq.almov(i1,ia)) then
			   movement(j,iphasek,ka)=1
!	           MVPF = MoveNoForLink(j,llink(j,ka))
!	           SignalPreventFor(llink(j,ka),MVPF) = 0  ! set the value to 1 is this is a permissive movement

        SignalPreventFor(j,ka) = 0 !allowed
        
		       MVPB = MoveNoBackLink(j,llink(j,ka))
             SignalPreventBack(ForToBackLink(llink(j,ka)),MVPB)=0
	        endif
            enddo 
	   
! -- make uturn movements allowed if it is specified in the signal 
! --


! need to allow uturns whenever a left turn is permitted 
              
      if(move(j,ka).eq.1.and.movement(j,iphasek,ka).eq.1) then
		  do kka =1,llink(j,nu_mv+1) 
	if(iunod(llink(j,kka)).eq.idnod(j).and.idnod(llink(j,kka))
     +  .eq.iunod(j)) then
                 movement(j,iphasek,kka)=1
		  
		 ! if(iunod(llink(j,ka)).eq.idnod(j).and.idnod(llink(j,ka)).eq.iunod(j)) then
          !      movement(j,iphasek,ka)=1


	   !        MVPF = MoveNoForLink(j,llink(j,ka))
	    !       SignalPreventFor(llink(j,ka),MVPF) = 0  ! set the value to 1 is this is a permissive movement
       
        SignalPreventFor(j,ka) = 0 !allowed
        

                 MVPB = MoveNoBackLink(j,llink(j,ka))
                 SignalPreventBack(ForToBackLink(llink(j,ka)),MVPB)=0
              endif
			enddo
		endif

        enddo
      enddo
! --
      
192   continue
     	endif !FBA Block
C        print *, 1005
! start reading Yield sign or two-way stop
     	if(SignCount.gt.0) then
C     	if(EOF(44)) then
C      write(911,*)'end of file when reading 2-way/yield control.dat'
C        stop
C	 endif
     	read(44,*,iostat=error)
     	if(error.ne.0) then
       	write(911,*) 'Error when reading 2-way/yield in control.dat'
	   stop
	 endif
	Print *,'Alex295-'
      allocate(SignData(SignCount),stat=error)
	Print *,'Alex296-'

	SignData(:)%node=0
	SignData(:)%NofMajor=0
	SignData(:)%NofMinor=0
 	Print *,'Alex297-'     

	allocate(SignApprh(SignCount), stat=error) 
      SignApprh(:)%major(1) = 0 ! max 4 major 4 minor approaches
      SignApprh(:)%major(2) = 0
	SignApprh(:)%major(3) = 0
      SignApprh(:)%major(4) = 0
      SignApprh(:)%minor(1) = 0
      SignApprh(:)%minor(2) = 0
	SignApprh(:)%minor(3) = 0
      SignApprh(:)%minor(4) = 0
      Print *,'Alex298-' 
      	do i = 1, SignCount
C        if(EOF(44)) then
C       write(911,*)'end of file when reading 2-way/yield control.dat'
C	      stop
C	    endif
        read(44,*,iostat=error) SignData(i)%node, SignData(i)%NofMajor, 
     +  SignData(i)%NofMinor
        if(error.ne.0) then
          write(911,*) 'Error when reading 2-way/yield in control.dat'
	      stop
	    endif
C        if(EOF(44)) then
C        write(911,*)'end of file when reading 2-way/yield control.dat'
C	      stop
C	    endif

        read(44,*,iostat=error) (TmpMJAph(j),j=1,2*SignData(i)%NofMajor) 
        if(error.ne.0) then
          write(911,*) 'Error when reading 2-way/yield in control.dat'
	      stop
	    endif
	    do k = 1, SignData(i)%NofMajor !get link number for major approach
	 SignApprh(i)%major(k) = GetFLinkFromNode(idnum(TmpMJAph(k*2-1))
     +   ,idnum(TmpMJAph(k*2)))
	    enddo
	read(44,*,iostat=error) (TmpMnAph(j),j=1,2*SignData(i)%NofMinor)
        if(error.ne.0) then
          write(911,*) 'Error when reading 2-way/yield in control.dat'
	      stop
	    endif
	    do k = 1, SignData(i)%NofMinor ! get link number for minor approach
	SignApprh(i)%minor(k) = GetFLinkFromNode(idnum(TmpMnAph(k*2-1))
     +  ,idnum(TmpMnAph(k*2)))
	    enddo
      enddo
 
 	 endif !SignCount.gt.0

! --
! --
! -- The next block is to get the prevented movements due to signal phasing
! -- SignalPreventBack(i,j)=1 means that the movement to link i from movement j is 
! -- prevented and 0 otherwise
! -- The difference between prevent and prevent1 is in the definition of i.
! -- SignalPreventFor carries the information in the forward star representation and
! -- SignalPreventBack for the backward-star representation.
! --
! --
! -- for the prevented movements, consider a very high penalty.
! --
         do i=1,noofarcs
           do kk=1,nu_mv
             if(SignalPreventFor(i,kk).eq.1) then
	         openalty(i,kk)=PenForPreventMove
	       endif

            if(SignalPreventBack(ForToBackLink(i),kk).eq.1) then
               penalty(ForToBackLink(i),kk)=PenForPreventMove  ! defined muc_mod_td
            endif

           enddo
         enddo
! --
! -- calculate the green time ratio (gcratio)
! -- consider different cases
! -- pretimed, actuated signal control
! --

        do i=1,noofarcs
          if(node(idnod(i),2).eq.4) then
            do k=kgpoint(idnod(i)),kgpoint(idnod(i)+1)-1
               do m=6,nsign(k,5)+5
                  if(i.eq.nsign(k,m)) then
        gcratio(i)=gcratio(i)+(float(nsign(k,3))/node(idnod(i),4))
                   endif
                end do
            end do
          endif
! --
! --
          if(node(idnod(i),2).eq.5) then
             do k=kgpoint(idnod(i)),kgpoint(idnod(i)+1)-1
                do m=6,nsign(k,5)+5
                   if(i.eq.nsign(k,m)) then
         gcratio(i)=gcratio(i)+(float(nsign(k,2))/node(idnod(i),4))
                   endif
                end do
             end do
          endif
        enddo 
!
! --
! -- Check if any control is found on the freeway.
C        print *, 1006
      do i = 1, noofarcs

!*********************************************

!link type 9: HOT / freeway
!link type 10: HOV / freeway

!        if(link_iden(i).eq.1) then
     	if(link_iden(i).eq.1.or.link_iden(i).eq.9.or.
     +  link_iden(i).eq.10) then
!*********************************************

	if(node(idnod(i),2).ne.2.and.node(idnod(i),2).ne.1) then
	write(911,'("Signs/Signals found on freeway section from"
     +  ,i7,"  to",i7)') nodenum(iunod(i)),nodenum(idnod(i))
           stop
		  endif
		endif
	  enddo
C        print *, 200
193 	format(11i4)
19 	format(i5,i2,i2,i4)
    	deallocate(CheckSignal)
    	deallocate(kgpointmp)
	return
    	end
