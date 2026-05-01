      subroutine deallocate_ksp2
      
	use muc_mod
      integer error

      deallocate(LabelPointerOut,stat=error)
      if(error.ne.0) then
        write(911,*) "deallocate LabelPointerOut error"
        stop
      endif 

      deallocate(PathPointerOut1,stat=error)
      if(error.ne.0) then
        write(911,*) "deallocate PathPointerOut1 error"
        stop
      endif
	
      deallocate(PathPointerOut2,stat=error)
      if(error.ne.0) then
        write(911,*) "deallocate PathPointerOut2 error"
        stop
      endif

      deallocate(PathPointerOut3,stat=error)
      if(error.ne.0) then
        write(911,*) "deallocate PathPointerOut3 error"
        stop
      endif

      deallocate(PathPointerOut4,stat=error)
      if(error.ne.0) then
        write(911,*) "deallocate PathPointerOut4 error"
        stop
      endif

	deallocate(cost,stat=error)
	if(error.ne.0) then
	  write(911,*) 'deallocate Cost error'
	  stop
	endif

	deallocate(LabelOut,stat=error)
      if(error.ne.0) then
        write(911,*) "deallocate LabelOut error"
        stop
	endif

      deallocate(LabelOutCost,stat=error)
      if(error.ne.0) then
        write(911,*) "deallocate labeloutcost error"
        stop
      endif

    	deallocate(labelforods,stat=error)
      if(error.ne.0) then
        write(911,*) "deallocate labelforods error"
        stop
      endif

      return
      end
