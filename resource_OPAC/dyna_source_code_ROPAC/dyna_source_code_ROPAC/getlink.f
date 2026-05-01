     	subroutine getlink(t,j,i,Culnk,Nlnk)
! --
! --   This subroutine combines a decision rule to model
! --   drivers' behavior under in-vehicle information.
! --   If divers donot have information, then follow originial paths.
! --
! -- This subroutine is called from vehicle_moving.
! -- This subroutine calls get_veh_path when the driver decides to switch.
! --
! -- INPUT :
! --    t : current clock time
! --    j : vehicle ID
! --    i : current link
! --
! -- OUTPUT
! --  Next link for vehicle j, and possibly the new path for it.
! --
    	use muc_mod
	use vector_mod
	integer Itp1,Nlnk,Culnk
    	logical Itp2
! --
! -- assign the current link i to icu 
! --
c	if(iteration.gt.0)print *, 'Alex220' .and.j.eq.295
    	icu=i
	Itp1=Culnk+1
	Itp2=.False.
	inode=nint(VhcAtt_Value(j,Itp1,1))
c	if(j.eq.42)then
c	if(iteration.gt.0.and.j.eq.213)print *,'Alex221-j=',j,inode,i,Itp1
c	endif
    	do k=backpointr(inode),backpointr(inode+1)-1
c	if(iteration.gt.0.and.j.eq.213)print *,
c     +  'Alex222',idnod(i),UNodeOfBackLink(k),k
      	if(idnod(i).eq.UNodeOfBackLink(k))then
        Nlnk=BackToForLink(k)
        Itp2=.True.
        exit
      	endif
    	enddo
c	if(iteration.gt.0.and.j.eq.213)print *, 'Alex230',Itp2
    	if(.not.Itp2)then
	write(911,*) 'Error in getlink'
	write(911,*) 'The likely reasons are:'
	write(911,*)'If the vehicle =  '
	write(911,*) j
	write(911,*) '  is a bus,the desination of'
	write(911,*) 'the bus doesnt have iflag_gen = 1 in network.dat'
c	if(iteration.gt.0.and.j.eq.213) print *,'Alex230-stop',Itp2	 
	   stop
	endif
! --
! -- 1. the non-equipped vehicles just use their current path. 
! -- 2. for the equipped vehicles, a new path will
! --    be assigned if they decide to switch according to the user 
! --    behavior rule.
! --
     	r=ran2(istrm)
!    call random_number(r)
! --
! -- For soda2 =1 or 3, a vehicle path is provided, then get the next
! -- link.  No need to check for switching.
!       if (soda2.eq.1.or.soda2.eq.3) go to 115
! --
c	if(iteration.gt.0)print *, 'Alex240' 
  	IF(info(j).eq.0.or.r.gt.compliance(j)) then ! no information or not compliant
! --
! -- In this part of the code, we check if the signal setting plan
! -- has changed and prevented a movement.  If so, we allow the vehicle
! -- to switch even though it does not have information.  Otherwise, the
! -- vehicle will continue on the current path. 
! --    
    	iback=ForToBackLink(Nlnk)
    	ipen=ForToBackLink(i)-backpointr(idnod(i))+1         
    	if(penalty(iback,ipen).gt.9990.and.isigcount.gt.1) then
       	call get_veh_path(j,i,1,Culnk)
    	endif
! -- 
! --
  	ELSE
c	if(iteration.gt.0)print *, 'Alex250' 
! --
! -- calculate the travel time on the current path (current_time)
! -- from the downstream node of the current link to the destination.
! --
    	current_time=0.0
    	do 3 k=Culnk,nnpath(j)-1
	     icuflag = 0
         nexnod=nint(VhcAtt_Value(j,k+1,1))
		 do l_p = 1,llink(icu,nu_mv+1)
            if(idnod(llink(icu,l_p)).eq.nexnod) then
	current_time=current_time+statmpt(llink(icu,l_p))+
     +  openalty(icu,l_p) ! -- add the travel time of the link to the current_time
            icuflag = 1
			icu = llink(icu,l_p)
			exit
			endif
		 enddo
		 if(icuflag.eq.0) then
		   print *, 'error icuflag'
		 endif
3    	continue
! --
c	if(iteration.gt.0)print *, 'Alex260' 
! --
! -- get the travel time on the current best path from the downstream
! -- node of link i to the destination of vehicle j (best).
! --
!5       nodecur=idnod(i)
5       movetmp=ForToBackLink(i)-backpointr(idnod(i))+1

        ict = 1

        know=labelpointerout(lt(j),ioc(j),MasterDest(jdest(j)),
     +  idnod(i),ict,1,movetmp)
        best=labeloutCost(lt(j),ioc(j),MasterDest(jdest(j)),
     +  idnod(i),ict,know,movetmp)
! --
! --  Check if the usr will switch according to the behavior rule.
! --  To switch two conditions have to be satisfied
! --  1. best < current_time*(1-relative indifference band)
! --  2. best < current_time - switching threshold
! --
c	if(iteration.gt.0)print *, 'Alex270' 
     	if((best.lt.current_time*(1-ribf(j))).and.
     +  (best.lt.current_time-bound)) then
! --
! --   switch to another path
! --
        call get_veh_path(j,i,1,Culnk)
        decision(j)=decision(j)+1
        if(switch(j).gt.0) switch(j)=(-1)*switch(j)
     	endif
! --
    	endif
! --
! -- get the next link for vehicle j according to its path.
! --
c	if(iteration.gt.0)print *, 'Alex280' 
        do k=backpointr(nint(VhcAtt_Value(j,Culnk+1,1))),
     +  backpointr(nint(VhcAtt_Value(j,Culnk+1,1))+1)-1
        if(idnod(i).eq.UNodeOfBackLink(k)) Nlnk=BackToForLink(k)
        enddo   
c	if(iteration.gt.0)print *, 'Alex290' 
      return
      end
