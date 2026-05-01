      subroutine get_veh_path(j,i,iselect,CurNode)
c --
c --   This subroutine assigns a path to the vehicle j.
c --   There are two cases for the path assignment :
c --   1. if iselect =0, then this is the initial path for the vehicle
c --   2. if iselsect >0, then this is a path switch
c --
c -- This subroutine is called from the following subroutines.
c -- 1. vehicle_moving : to assign an initial path to the vehicle
c -- 2. getlink : to assign the vehicle to the best path when the vehicle is switching paths.
c -- 3. vms_path : to assign a new path to the vehicles following the VMS sign. 
c -- 4. vms_divert : to assign a new path to the vehicles following the VMS sign. 
c --
c -- This subroutine does not call any other subroutines.
c --
c -- INPUT
c --    j : vehicle ID
c --    i : current link
c -- iselect : see the description above
c --
c -- OUTPUT
c --    path for vehicle j
c --  
      use muc_mod
	use vector_mod
	integer::pathttmp(1000)=0
      integer Index1D,CurNode
      real value 
c --
c -- If the vehicle is assigned to a specific path number (iselect), then
c -- the subroutine will assign the vehicle to that specific path.
c --
c -- If the vehicle will be assigned an initial path, then this will depend
c -- on the variable "ipinit": if ipinit=0 assign to a randomly selected 
c --                           path out of the "kay" paths
c --  iselect could take 3 values
c --  1: best path
c --  0: random assign
c --  others: specific path
c --
	
c	print *, 'Alex1113241'
      	pathttmp(:) = 0
      	if(iselect.eq.1) then
         ibest=iuserpath(j)
      	elseif(iselect.eq.0) then
         call DYNA_random_number(r1,7)
         ibest=nint(r1*kay)
         if(ibest.gt.kay) ibest=kay
      	else
         ibest=iselect
      	endif
c  -- 
c  -- define destination and origin
c  --
          icu1=i
          ifrom=idnod(i)
          ito=MasterDest(jdest(j))
          ict = 1
c  --
c  -- follow the shortest path code
c  --
c	print *, 'Alex1113242'
            mov=ForToBackLink(icu1)-backpointr(ifrom)+1
c           know=labelpointerout(lt(j),ioc(j),ito,ifrom,ict,ibest,mov)
            know=ibest
            k=CurNode
c --
c --
c	print *, 'Alex1113243'

        do 20 while(ifrom.ne.destination(ito))
c	print *, 'Alex111324300'
             if(know.eq.0) then
               know=1
             endif
c	print *, 'Alex111324301'
             Index1D = k
c	print *, 'Alex1113243011'
             value = float(ifrom)
c	if(j.eq.42)then
c	print *, 'Alex012-here',' j=',j,Index1D,value
c	endif
	if(value.lt.0.1)then
	stop
	endif
             call VhcAtt_Insert(j,Index1D,1,value)
c	print *, 'Alex302-here=',VhcAtt_Array(j)%PSize
	     pathttmp(k) = ifrom
             k=k+1
             ifromtmp=ifrom
             ktemp=know
             movetemp=mov
             icttemp=ict
             ict=1

c	print *, 'Alex11132431'

         mov=pathpointerout3(lt(j),ioc(j),ito,
     *                     ifromtmp,icttemp,ktemp,movetemp)
         know=pathpointerout2(lt(j),ioc(j),ito,
     *                      ifromtmp,icttemp,ktemp,movetemp)
         ifrom=pathpointerout1(lt(j),ioc(j),ito,
     *                      ifromtmp,icttemp,ktemp,movetemp)

          if(mov.lt.1.or.know.lt.1.or.ifrom.lt.1)then

c	print *, 'Alex11132432'

      	write(911,*) 'Error!'
	write(911,*) 
	write(911,*) 'No path exists from:'
	!write(911,*) 'Node',ifromtmp,'    to destination node'

       	write(911,*) 'Node',nodenum(ifromtmp),' to destination node'
     +	,destination(MasterDest(jdest(j))),
     + '   in zone',jdest(j)

	!write(911,*) 'error in get_veh_path'
      	write(911,*) 'For vehicle number',j
	write(911,*) 'Generation link ',nodenum(iunod(isec(j))),
     +	'    ->',nodenum(idnod(isec(j)))

c	print *, 'Alex11132433'

      	write(911,*) 
	write(911,*) 'Possible reasons:'
	write(911,*) 'No physical path exists, or'
	write(911,*)'There is a prevented movement in movement.dat, or'
      	write(911,*)'There is a prevented movement due to signal setting'
	write(911,*)
	write(911,*) 'If this error resulted from a detour VMS, then	
     + check the sequence of nodes'
      	write(911,*) 'along the detour path'

c	print *, 'Alex11132434'

!	 write(911,*) 'check generation link ',nodenum(iunod(isec(j))),
!     +'->', nodenum(idnod(isec(j)))
!       write(911,*) 'destination zone',jdest(j)
!       write(911,*) 'destination node',
!     +  destination(MasterDest(jdest(j)))
!	     write(911,*) 'pathttmp(k)', pathttmp
           stop
	     exit
          endif 

c	print *, 'Alex11132435'

20      continue
c	print *, 'Alex1113244'

      	Index1D = k
      	value = float(destination(MasterDest(jdest(j))))
c	if(j.eq.42)then
c	print *, 'Alex303-here=',j,Index1D,value
c	endif
	if(value.lt.0.1)then
	stop
	endif
      call VhcAtt_Insert(j,Index1D,1,value)
c	print *, 'Alex304-here=',VhcAtt_Array(j)%PSize
	call VhcAtt_Clear(j,Index1D+1)
c	print *, 'Alex305-here=',VhcAtt_Array(j)%PSize
	pathttmp(k)=destination(MasterDest(jdest(j)))

      	nnpath(j)=k

      	if(CurNode.eq.1) then
          call CheckImpact(pathttmp,j,CurNode-1) ! pass 0 as the last arg
	endif
c	print *, 'Alex306-here=',VhcAtt_Array(j)%PSize
      	return
      	end  
